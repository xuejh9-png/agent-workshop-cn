import os, tempfile, unittest
from pathlib import Path
from file_tools import ScopedFiles

class ScopeTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=self.base/'spaces'/'one';self.root.mkdir(parents=True);self.outside=self.base/'outside';self.outside.mkdir();(self.outside/'sentinel.txt').write_text('outside')
    def tearDown(self):self.temp.cleanup()
    def test_read_create_real_text(self):
        scope=ScopedFiles(self.root,True);scope.create('中文.md','可读的中文');self.assertEqual(scope.read('中文.md'),'可读的中文')
    def test_no_write_without_grant(self):
        with self.assertRaises(PermissionError):ScopedFiles(self.root).create('x.txt','x')
    def test_no_overwrite(self):
        scope=ScopedFiles(self.root,True);scope.create('x.txt','first')
        with self.assertRaises(FileExistsError):scope.create('x.txt','second')
        self.assertEqual(scope.read('x.txt'),'first')
    def test_reject_escape_hidden_and_binary(self):
        scope=ScopedFiles(self.root,True)
        for name in ['../sentinel.txt','/etc/hosts','.env','a/.secret.txt','data.pdf']:
            with self.assertRaises(ValueError):scope.read(name)
    def test_root_symlink_rejected(self):
        link=self.base/'link';link.symlink_to(self.outside)
        with self.assertRaises(OSError):ScopedFiles(link)
    def test_ancestor_symlink_rejected(self):
        (self.root.parent).rename(self.base/'old-spaces');(self.root.parent).symlink_to(self.outside);(self.outside/'one').mkdir()
        with self.assertRaises(OSError):ScopedFiles(self.root,True)
    def test_open_descriptor_survives_ancestor_replacement(self):
        scope=ScopedFiles(self.root,True);self.root.parent.rename(self.base/'old-spaces');self.root.parent.symlink_to(self.outside);(self.outside/'one').mkdir();scope.create('new.txt','safe');self.assertFalse((self.outside/'one'/'new.txt').exists());self.assertTrue((self.base/'old-spaces'/'one'/'new.txt').exists())
    def test_symlink_and_hardlink_files_rejected(self):
        (self.root/'sym.txt').symlink_to(self.outside/'sentinel.txt');os.link(self.outside/'sentinel.txt',self.root/'hard.txt');scope=ScopedFiles(self.root)
        for name in ['sym.txt','hard.txt']:
            with self.assertRaises((OSError,ValueError)):scope.read(name)
    def test_size_limit(self):
        with self.assertRaises(ValueError):ScopedFiles(self.root,True).create('large.txt','a'*(256*1024+1))

if __name__=='__main__':unittest.main()
