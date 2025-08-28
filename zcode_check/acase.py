def fred(x):
    match x:
        case 1:
            print("1")
            return
        case 2:
            print("2")
            # 不 return，继续执行后面的代码
        case 3:
            print("3")
            return

    print("out")


def main():
    fred(1)
    fred(2)
    fred(3)


main()
